require 'spec_helper'
require 'rack/test'
require 'json'
require_relative '../app/app'

RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'returns 400 when content is missing' do
      post '/analyze', { path: 'file.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when old_content or new_content is missing' do
      post '/diff', { old_content: 'old' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing old_content or new_content')
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing files array')
    end
  end

  describe 'private helpers' do
    let(:api_instance) { PolyglotAPI.new }

    describe '#detect_language' do
      it 'detects ruby from file extension' do
        expect(api_instance.send(:detect_language, 'file.rb')).to eq('ruby')
      end

      it 'detects python from file extension' do
        expect(api_instance.send(:detect_language, 'script.py')).to eq('python')
      end

      it 'returns unknown for unrecognized extensions' do
        expect(api_instance.send(:detect_language, 'archive.xyz')).to eq('unknown')
      end
    end

    describe '#calculate_quality_score' do
      it 'returns 0.0 when metrics is nil' do
        expect(api_instance.send(:calculate_quality_score, nil, { 'score' => 90 })).to eq(0.0)
      end

      it 'returns 0.0 when review has error' do
        expect(api_instance.send(:calculate_quality_score, { 'complexity' => 1 }, { 'error' => 'fail' })).to eq(0.0)
      end

      it 'clamps to 100 when score exceeds 100' do
        score = api_instance.send(:calculate_quality_score, { 'complexity' => 0 }, { 'score' => 150, 'issues' => [] })
        expect(score).to eq(100)
      end

      it 'computes expected score with penalties' do
        score = api_instance.send(:calculate_quality_score, { 'complexity' => 2 }, { 'score' => 95, 'issues' => ['a'] })
        expect(score).to eq(25.0)
      end

      it 'clamps to 0 when penalties exceed score' do
        score = api_instance.send(:calculate_quality_score, { 'complexity' => 10 },
                                  { 'score' => 20, 'issues' => %w[a b] })
        expect(score).to eq(0)
      end
    end

    describe '#calculate_dashboard_health_score' do
      it 'returns 0.0 when file_stats has error' do
        expect(api_instance.send(:calculate_dashboard_health_score, { 'error' => 'x' },
                                 { 'average_score' => 80 })).to eq(0.0)
      end

      it 'clamps between 0 and 100' do
        high = api_instance.send(:calculate_dashboard_health_score, { 'total_files' => 1 },
                                 { 'average_score' => 150, 'total_issues' => 0, 'average_complexity' => 0 })
        low = api_instance.send(:calculate_dashboard_health_score, { 'total_files' => 1 },
                                { 'average_score' => 5, 'total_issues' => 100, 'average_complexity' => 10 })
        expect(high).to eq(100)
        expect(low).to eq(0)
      end

      it 'computes expected health score' do
        file_stats = { 'total_files' => 4 }
        review_stats = { 'average_score' => 80.0, 'total_issues' => 4, 'average_complexity' => 0.5 }
        score = api_instance.send(:calculate_dashboard_health_score, file_stats, review_stats)
        expect(score).to eq(63.0)
      end
    end
  end
end