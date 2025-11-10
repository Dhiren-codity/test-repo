require 'json'

class RequestValidator
  VALIDATION_ERRORS = []
  MAX_CONTENT_SIZE = 1_000_000
  MAX_PATH_LENGTH = 500
  ALLOWED_LANGUAGES = %w[go python ruby javascript typescript java].freeze

  class ValidationError < StandardError
    attr_reader :field, :reason

    def initialize(field, reason)
      @field = field
      @reason = reason
      super("Validation failed for #{field}: #{reason}")
    end

    def to_hash
      { field: @field, reason: @reason }
    end
  end

  def self.validate_analyze_request(params)
    errors = []

    content = params['content'] || params[:content]
    path = params['path'] || params[:path]

    if content.nil? || content.empty?
      errors << ValidationError.new('content', 'Content is required and cannot be empty')
    elsif content.length > MAX_CONTENT_SIZE
      errors << ValidationError.new('content', "Content exceeds maximum size of #{MAX_CONTENT_SIZE} bytes")
    elsif contains_null_bytes?(content)
      errors << ValidationError.new('content', 'Content contains invalid null bytes')
    end

    if path && path.length > MAX_PATH_LENGTH
      errors << ValidationError.new('path', "Path exceeds maximum length of #{MAX_PATH_LENGTH} characters")
    end

    if path && contains_path_traversal?(path)
      errors << ValidationError.new('path', 'Path contains potential directory traversal')
    end

    log_validation_errors(errors) unless errors.empty?

    errors
  end

  def self.validate_diff_request(params)
    errors = []

    old_content = params['old_content'] || params[:old_content]
    new_content = params['new_content'] || params[:new_content]

    if old_content.nil? || old_content.empty?
      errors << ValidationError.new('old_content', 'Old content is required')
    elsif old_content.length > MAX_CONTENT_SIZE
      errors << ValidationError.new('old_content', "Old content exceeds maximum size")
    end

    if new_content.nil? || new_content.empty?
      errors << ValidationError.new('new_content', 'New content is required')
    elsif new_content.length > MAX_CONTENT_SIZE
      errors << ValidationError.new('new_content', "New content exceeds maximum size")
    end

    log_validation_errors(errors) unless errors.empty?

    errors
  end

  def self.validate_metrics_request(params)
    errors = []

    content = params['content'] || params[:content]

    if content.nil? || content.empty?
      errors << ValidationError.new('content', 'Content is required for metrics')
    elsif content.length > MAX_CONTENT_SIZE
      errors << ValidationError.new('content', "Content exceeds maximum size")
    end

    log_validation_errors(errors) unless errors.empty?

    errors
  end

  def self.sanitize_input(input)
    return nil if input.nil?
    return input unless input.is_a?(String)

    sanitized = input.gsub(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/, '')
    sanitized = sanitized.force_encoding('UTF-8')
    sanitized.valid_encoding? ? sanitized : sanitized.encode('UTF-8', invalid: :replace, undef: :replace)
  end

  def self.get_validation_errors
    VALIDATION_ERRORS.dup
  end

  def self.clear_validation_errors
    VALIDATION_ERRORS.clear
  end

  private

  def self.contains_null_bytes?(content)
    content.include?("\x00")
  end

  def self.contains_path_traversal?(path)
    path.include?('..') || path.include?('~/')
  end

  def self.log_validation_errors(errors)
    timestamp = Time.now.iso8601
    errors.each do |error|
      VALIDATION_ERRORS << {
        timestamp: timestamp,
        field: error.field,
        reason: error.reason
      }
    end
    keep_recent_errors
  end

  def self.keep_recent_errors
    VALIDATION_ERRORS.shift while VALIDATION_ERRORS.length > 100
  end
end
